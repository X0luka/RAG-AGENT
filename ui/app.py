"""Streamlit UI for the RAG Memory Assistant."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")


def http_client() -> httpx.Client:
    """Create a synchronous API client."""
    return httpx.Client(base_url=API_BASE, timeout=120)


async def stream_query_events(query: str, **kwargs) -> AsyncIterator[tuple[str, dict]]:
    """Call /api/query and parse server-sent events."""
    async with httpx.AsyncClient(base_url=API_BASE, timeout=120) as client:
        async with client.stream("POST", "/api/query", json={"query": query, **kwargs}) as response:
            response.raise_for_status()
            event_type = None
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:") and event_type:
                    yield event_type, json.loads(line[5:].strip())


def sync_stream_query(query: str, **kwargs) -> Iterator[tuple[str, dict]]:
    """Bridge the async SSE client into Streamlit's sync runtime."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    agen = stream_query_events(query, **kwargs)
    try:
        while True:
            try:
                yield loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.run_until_complete(agen.aclose())
        loop.close()


def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("total_cost", 0.0)


def _api_error(exc: Exception) -> None:
    st.error(str(exc))


def _post_feedback(interaction_id: int, feedback: int) -> None:
    try:
        with http_client() as client:
            response = client.post(
                "/api/feedback",
                json={"interaction_id": interaction_id, "feedback": feedback},
            )
            response.raise_for_status()
        st.toast("Feedback saved")
    except httpx.HTTPError as exc:
        _api_error(exc)


def _render_citations(citations: list[dict]) -> None:
    if not citations:
        return
    with st.expander(f"Sources ({len(citations)})"):
        for citation in citations:
            page_str = f" p.{citation['page']}" if citation.get("page") else ""
            st.markdown(f"**[{citation['source_id']}]** `{citation['source']}`{page_str}")
            st.caption(citation.get("text_preview", ""))


def chat_page() -> None:
    """Render the chat page."""
    _init_state()
    st.title("Chat")
    with st.sidebar:
        mode = st.segmented_control("Mode", ["Strong", "Cheap"], default="Strong")
        include_history = st.toggle("Use history", value=True)
        st.metric("Session cost", f"${st.session_state.total_cost:.4f}")

    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                _render_citations(message.get("citations", []))
                interaction_id = message.get("interaction_id")
                if interaction_id:
                    cols = st.columns([1, 1, 8])
                    if cols[0].button("👍", key=f"up-{index}"):
                        _post_feedback(interaction_id, 1)
                    if cols[1].button("👎", key=f"down-{index}"):
                        _post_feedback(interaction_id, -1)

    prompt = st.chat_input("Ask your knowledge base")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        text_placeholder = st.empty()
        answer_parts: list[str] = []
        citations: list[dict] = []
        usage: dict[str, Any] = {}
        interaction_id = None

        for event_type, data in sync_stream_query(
            prompt,
            include_history=include_history,
            use_cheap_model=mode == "Cheap",
        ):
            if event_type == "start":
                interaction_id = data.get("interaction_id")
            elif event_type == "delta":
                answer_parts.append(data.get("content") or "")
                text_placeholder.markdown("".join(answer_parts))
            elif event_type == "citations":
                citations = data.get("citations") or []
            elif event_type == "done":
                usage = data.get("usage") or {}
            elif event_type == "error":
                st.error(f"{data.get('error_code')}: {data.get('error_message')}")
                return

        answer = "".join(answer_parts)
        text_placeholder.markdown(answer)
        _render_citations(citations)
        cost = float(usage.get("cost_usd") or 0.0)
        st.session_state.total_cost += cost
        if usage:
            st.caption(
                f"tokens={usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)} "
                f"cost=${cost:.4f}"
            )
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "citations": citations,
                "interaction_id": interaction_id,
            }
        )


def history_page() -> None:
    """Render interaction history."""
    st.title("History")
    feedback_filter = st.selectbox("Feedback", ["All", "👍", "👎", "Unrated"])
    page_size = st.number_input("Page size", min_value=5, max_value=100, value=20, step=5)
    try:
        with http_client() as client:
            response = client.get("/api/history", params={"page": 1, "page_size": int(page_size)})
            response.raise_for_status()
            items = response.json()["items"]
    except httpx.HTTPError as exc:
        _api_error(exc)
        return

    def include(item: dict) -> bool:
        feedback = item.get("feedback")
        return (
            feedback_filter == "All"
            or (feedback_filter == "👍" and feedback == 1)
            or (feedback_filter == "👎" and feedback == -1)
            or (feedback_filter == "Unrated" and feedback is None)
        )

    for item in [item for item in items if include(item)]:
        with st.expander(f"{item['timestamp']} · {item['query']}"):
            st.markdown(item["answer"])
            st.caption(f"cost=${item['cost_usd']:.4f} feedback={item.get('feedback')}")
            try:
                with http_client() as client:
                    detail = client.get(f"/api/history/{item['id']}")
                    detail.raise_for_status()
                    chunks = detail.json().get("retrieved_chunks", {})
                st.json(chunks)
            except httpx.HTTPError:
                pass


def documents_page() -> None:
    """Render document management."""
    st.title("Documents")
    try:
        with http_client() as client:
            response = client.get("/api/documents")
            response.raise_for_status()
            documents = response.json()["items"]
    except httpx.HTTPError as exc:
        _api_error(exc)
        documents = []

    uploaded = st.file_uploader("Upload source file")
    source_type = st.selectbox("Type", ["paper", "code", "article", "transcript"])
    force = st.checkbox("Force reingest", value=False)
    if uploaded and st.button("Ingest"):
        raw_path = Path("data/raw") / uploaded.name
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(uploaded.getbuffer())
        try:
            with http_client() as client:
                response = client.post(
                    "/api/ingest",
                    json={"path": raw_path.as_posix(), "source_type": source_type, "force": force},
                )
                response.raise_for_status()
            st.success(response.json()["message"])
            st.rerun()
        except httpx.HTTPError as exc:
            _api_error(exc)

    st.divider()
    for document in documents:
        cols = st.columns([4, 1, 1, 1])
        cols[0].markdown(f"`{document['source']}`")
        cols[1].text(document["source_type"])
        cols[2].text(f"{document['chunk_count']} chunks")
        if cols[3].button("Delete", key=f"delete-{document['id']}"):
            try:
                with http_client() as client:
                    response = client.delete(f"/api/documents/{document['id']}")
                    response.raise_for_status()
                st.success("Deleted")
                st.rerun()
            except httpx.HTTPError as exc:
                _api_error(exc)


def main() -> None:
    """Run the Streamlit app."""
    st.set_page_config(page_title="RAG Memory Assistant", layout="wide")
    pages = [
        st.Page(chat_page, title="Chat"),
        st.Page(history_page, title="History"),
        st.Page(documents_page, title="Documents"),
    ]
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
