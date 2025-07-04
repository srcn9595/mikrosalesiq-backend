"""
Plan adındaki async tool → jobs[].type eşlemesi
Burada listelenen tool’lar kuyruğa gider, worker ile sonuçlanır.
"""
ASYNC_TOOLS: dict[str, str] = {
    "get_mini_rag_summary": "mini_rag",
    "enqueue_mini_rag":     "mini_rag",
    "call_insights":        "call_insights",
    "download_audio":       "download_audio",
    # ileride async çalışan her yeni tool’u buraya ekleyin
}
