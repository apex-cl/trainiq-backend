"""
Schnelltest: OpenRouter LLM (Chat + Streaming + Agent)
Führe aus mit: python3 test_llm.py
"""

import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
MODEL = os.getenv("LLM_MODEL", "qwen/qwen3.6-plus:free")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://integrate.api.nvidia.com/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "") or API_KEY
EMBEDDING_MODEL = os.getenv("LLM_EMBEDDING_MODEL", "")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://trainiq.app",
    "X-Title": "TrainIQ",
}

OK = "✅"
FAIL = "❌"
INFO = "ℹ️ "


# ─── TEST 1: Einfacher Chat via httpx ────────────────────────────────────────
async def test_raw_chat():
    print("\n─── Test 1: Raw HTTP Chat (httpx) ───")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers=HEADERS,
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": "Antworte nur mit: OK"}],
                    "max_tokens": 20,
                },
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            # Reasoning-Modelle liefern content + reasoning getrennt
            answer = (msg.get("content") or "").strip()
            reasoning_preview = (msg.get("reasoning") or "")[:50]
            print(f"{OK} Antwort: '{answer}' | Status: {resp.status_code}")
            if reasoning_preview:
                print(f"{INFO} Reasoning (intern): '{reasoning_preview}...'")
            return True
    except Exception as e:
        print(f"{FAIL} Fehler: {e}")
        return False


# ─── TEST 2: LangChain ChatOpenAI ────────────────────────────────────────────
async def test_langchain_chat():
    print("\n─── Test 2: LangChain ChatOpenAI ───")
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            max_tokens=50,
            temperature=0.3,
        )
        response = await llm.ainvoke([HumanMessage(content="Was ist 2+2? Nur die Zahl.")])
        print(f"{OK} Antwort: '{response.content.strip()}'")
        print(f"{INFO} Token-Usage: {response.usage_metadata}")
        return True
    except Exception as e:
        print(f"{FAIL} Fehler: {e}")
        return False


# ─── TEST 3: LangChain Streaming ─────────────────────────────────────────────
async def test_langchain_streaming():
    print("\n─── Test 3: LangChain Streaming ───")
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        llm = ChatOpenAI(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            max_tokens=80,
            temperature=0.5,
            streaming=True,
        )
        chunks = []
        async for chunk in llm.astream([HumanMessage(content="Zähle von 1 bis 5.")]):
            chunks.append(chunk.content)
        full = "".join(chunks).strip()
        print(f"{OK} Stream-Antwort: '{full[:80]}'")
        print(f"{INFO} Chunks empfangen: {len(chunks)}")
        return True
    except Exception as e:
        print(f"{FAIL} Fehler: {e}")
        return False


# ─── TEST 4: LangChain Agent mit Tool ────────────────────────────────────────
async def test_langchain_agent():
    print("\n─── Test 4: LangChain Agent mit Tool-Aufruf ───")
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.tools import tool
        from langchain_core.messages import HumanMessage, ToolMessage

        @tool
        def get_recovery_score() -> str:
            """Gibt den heutigen Recovery Score des Athleten zurück."""
            return '{"recovery_score": 82, "label": "Gut", "hrv_ms": 54, "ruhepuls": 48}'

        llm = ChatOpenAI(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            max_tokens=300,
            temperature=0.3,
        )
        llm_with_tools = llm.bind_tools([get_recovery_score])

        # Schritt 1: LLM entscheidet ob Tool gebraucht wird
        messages = [HumanMessage(content="Wie ist mein heutiger Recovery Score? Gib eine kurze Empfehlung.")]
        ai_msg = await llm_with_tools.ainvoke(messages)
        messages.append(ai_msg)

        tool_calls = ai_msg.tool_calls
        if tool_calls:
            print(f"{OK} Tool-Aufruf erkannt: {tool_calls[0]['name']}")
            # Schritt 2: Tool ausführen
            for tc in tool_calls:
                result = get_recovery_score.invoke(tc["args"])
                messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
            # Schritt 3: Finale Antwort
            final = await llm.ainvoke(messages)
            print(f"{OK} Agent-Antwort: '{final.content[:150].strip()}'")
        else:
            content = (ai_msg.content or "").strip()
            print(f"{INFO} Kein Tool-Aufruf — direktantwort: '{content[:100]}'")
        return True
    except Exception as e:
        print(f"{FAIL} Fehler: {e}")
        return False


# ─── TEST 5: Embedding (NVIDIA NIM) ──────────────────────────────────────────
async def test_embedding():
    print("\n─── Test 5: Embeddings (NVIDIA NIM) ───")
    if not EMBEDDING_MODEL:
        print(f"{INFO} LLM_EMBEDDING_MODEL nicht gesetzt → Embedding-Test übersprungen")
        return None
    if not EMBEDDING_API_KEY or EMBEDDING_API_KEY == API_KEY:
        print(f"{INFO} Kein separater EMBEDDING_API_KEY → nutze LLM-Key für Test")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{EMBEDDING_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {EMBEDDING_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": "Der Athlet hat heute 8 Stunden geschlafen",
                    "input_type": "passage",
                    "encoding_format": "float",
                },
            )
            resp.raise_for_status()
            embedding = resp.json()["data"][0]["embedding"]
            print(f"{OK} Embedding erhalten | Dimensionen: {len(embedding)} | Erste 3 Werte: {embedding[:3]}")
            if len(embedding) == 1024:
                print(f"{OK} Dimension 1024 ✓ passt zur pgvector-DB")
            else:
                print(f"⚠️  Dimension {len(embedding)} ≠ 1024 — DB-Migration nötig!")
            return True
    except Exception as e:
        print(f"{FAIL} Fehler: {e}")
        if "401" in str(e) or "403" in str(e):
            print(f"{INFO} Tipp: EMBEDDING_API_KEY in .env setzen (build.nvidia.com → kostenloser API-Key)")
        return False


# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n{'='*55}")
    print(f"  TrainIQ LLM Test")
    print(f"  Model:   {MODEL}")
    print(f"  BaseURL: {BASE_URL}")
    print(f"  Embed:   {EMBEDDING_MODEL or '(nicht konfiguriert)'}")
    print(f"{'='*55}")

    results = await asyncio.gather(
        test_raw_chat(),
        return_exceptions=True,
    )

    # Sequentiell damit Output lesbar bleibt
    await test_langchain_chat()
    await test_langchain_streaming()
    await test_langchain_agent()
    await test_embedding()

    print(f"\n{'='*55}")
    print("  Tests abgeschlossen")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(main())
