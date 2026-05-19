import asyncio
import json
import os
from pathlib import Path

from google import genai

TEST_CASES_PATH = Path(__file__).parent / "test_cases.json"

async def run_baseline():
    test_cases = json.loads(TEST_CASES_PATH.read_text())
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY not set")
        return

    client = genai.Client(api_key=api_key)

    print(f"Running baseline on {len(test_cases)} cases...")
    
    for i, tc in enumerate(test_cases):
        try:
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash",
                contents=tc["query"],
                config={"temperature": 0.0}
            )
            ans = resp.text.strip() if resp.text else ""
            print(f"[{tc['id']}] {ans[:50]}...")
        except Exception as e:
            print(f"[{tc['id']}] Error: {e}")
            
        if i < len(test_cases) - 1:
            await asyncio.sleep(4)

if __name__ == "__main__":
    asyncio.run(run_baseline())
