"""
Seed script — embeds 30 documents using Gemini text-embedding-004
and inserts them into the document_chunks table.

Uses task_type="retrieval_document" for seeding (spec requirement).
Retrieval queries use task_type="retrieval_query".

Run after: alembic upgrade head
Usage: python scripts/seed_kb.py
"""
import asyncio
import os
import sys
import uuid

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import google.generativeai as genai
from sqlalchemy import text

SEED_DOCUMENTS = [
    # BASELINE coverage (10 docs)
    {"content": "Paris is the capital city of France. The population of the city proper is approximately 2.1 million, while the greater metropolitan area has over 12 million inhabitants.", "source_url": "seed/paris_france"},
    {"content": "Water boils at 100 degrees Celsius (212 degrees Fahrenheit) at standard atmospheric pressure of 101.325 kPa. At higher altitudes, the boiling point decreases.", "source_url": "seed/water_boiling"},
    {"content": "Python was created by Guido van Rossum and was first released in 1991. It is a high-level, interpreted, general-purpose programming language.", "source_url": "seed/python_history"},
    {"content": "The Great Wall of China has a total length of approximately 21,196 kilometers (13,171 miles) according to a 2012 archaeological survey by China's National Cultural Heritage Administration.", "source_url": "seed/great_wall"},
    {"content": "The speed of light in a vacuum is exactly 299,792,458 metres per second (approximately 3×10^8 m/s or 186,000 miles per second). This is a fundamental physical constant.", "source_url": "seed/speed_of_light"},
    {"content": "FastAPI is a modern, fast web framework for building APIs with Python 3.7+ based on standard Python type hints. It uses async/await natively and auto-generates OpenAPI documentation.", "source_url": "seed/fastapi"},
    {"content": "PostgreSQL is a powerful open-source relational database system. The pgvector extension adds support for vector similarity search, enabling efficient nearest-neighbor queries for embedding-based retrieval.", "source_url": "seed/postgresql_pgvector"},
    {"content": "Redis is an in-memory data structure store used as a database, cache, message broker, and streaming engine. It supports pub/sub messaging, which enables real-time event broadcasting.", "source_url": "seed/redis"},
    {"content": "Retrieval-Augmented Generation (RAG) combines information retrieval with language model generation. Documents are embedded into vectors, relevant chunks are retrieved for a query, and the LLM generates answers grounded in those chunks.", "source_url": "seed/rag"},
    {"content": "Multi-agent systems consist of multiple AI agents that perceive their environment and take actions. A shared context (blackboard) pattern allows agents to communicate through a shared data structure without calling each other directly.", "source_url": "seed/multi_agent"},
    
    # AMBIGUOUS coverage (10 docs)
    {"content": "GDPR (General Data Protection Regulation) applies to all organizations processing EU citizens data, regardless of where the organization is located. Fines can reach 4% of global annual revenue.", "source_url": "ambiguous/gdpr_detail"},
    {"content": "Machine learning overfitting occurs when a model learns training data noise rather than underlying patterns. Mitigation includes regularization, dropout, early stopping, and cross-validation.", "source_url": "ambiguous/ml_overfitting"},
    {"content": "Quantum entanglement allows particles to share quantum states instantaneously across distance. It does not allow faster-than-light communication due to the no-communication theorem.", "source_url": "ambiguous/quantum_entanglement"},
    {"content": "Supply chain resilience strategies include dual sourcing, safety stock buffers, demand forecasting, and supplier diversification.", "source_url": "ambiguous/supply_chain_detail"},
    {"content": "Network errors can result from many causes: DNS resolution failures, packet loss, firewall rules, misconfigured routing, hardware faults, or bandwidth saturation.", "source_url": "seed/network_errors"},
    {"content": "Open source software licenses vary significantly. MIT and Apache 2.0 are highly permissive, allowing almost unrestricted use, while the GPL is copyleft, requiring derived works to adopt the same license.", "source_url": "seed/oss_licenses"},
    {"content": "Agile methodologies prioritize iterative development, while Waterfall relies on rigid sequential phases. Scrum is an Agile framework involving sprints, scrums, and backlogs.", "source_url": "seed/agile_vs_waterfall"},
    {"content": "Cloud computing models include Infrastructure as a Service (IaaS), Platform as a Service (PaaS), and Software as a Service (SaaS). AWS EC2 is IaaS, whereas Google App Engine is PaaS.", "source_url": "seed/cloud_models"},
    {"content": "Microservices architecture breaks down a monolithic application into small, independent services. This improves scalability and deployment flexibility but increases networking and operational complexity.", "source_url": "seed/microservices"},
    {"content": "OAuth 2.0 is an authorization framework that enables applications to obtain limited access to user accounts. JWT (JSON Web Tokens) are commonly used as access tokens within OAuth flows.", "source_url": "seed/oauth_jwt"},

    # ADVERSARIAL coverage (10 docs)
    {"content": "Albert Einstein won the Nobel Prize in Physics in 1921 for his discovery of the photoelectric effect, not for the theory of relativity.", "source_url": "adversarial/einstein_nobel"},
    {"content": "Prompt injection is an attack where malicious input attempts to override an AI system's instructions. Defense layers include input sanitization, spotlighting, and output validation.", "source_url": "adversarial/prompt_injection"},
    {"content": "The United States has never annexed Canada. Canada is a fully independent sovereign nation. The Canada Act 1982 patriated the Canadian constitution from the UK.", "source_url": "adversarial/canada_sovereignty"},
    {"content": "Mars shows strong evidence of ancient water activity including dried riverbeds, delta formations, and hydrated mineral deposits.", "source_url": "adversarial/mars_water_evidence"},
    {"content": "Current liquid water on the Martian surface has not been confirmed. Some radar reflections suggest possible subsurface water but this interpretation remains scientifically contested.", "source_url": "adversarial/mars_water_contested"},
    {"content": "There are 195 recognized countries in the world as of 2024, including 193 UN member states and 2 observer states.", "source_url": "adversarial/country_count"},
    {"content": "Napoleon Bonaparte was not unusually short. He was around 5 feet 6 inches (1.68 meters) tall, which was average or slightly above average for a Frenchman of his time.", "source_url": "seed/napoleon_height"},
    {"content": "Bulls are not angered by the color red. Like other cattle, bulls are dichromats and cannot clearly distinguish red. They are provoked by the movement of the matador's cape.", "source_url": "seed/bulls_color_red"},
    {"content": "Different parts of the human tongue do not detect different tastes exclusively. The 'tongue map' is a misconception; all taste sensations come from all regions of the tongue.", "source_url": "seed/taste_map"},
    {"content": "Humans do not use only 10% of their brains. Brain imaging shows that almost all regions of the brain are active even during routine tasks, and every part has a known function.", "source_url": "seed/ten_percent_brain"},
]


async def seed() -> None:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set")
        sys.exit(1)

    genai.configure(api_key=api_key)

    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        seeded = 0
        skipped = 0

        if len(SEED_DOCUMENTS) != 30:
            print(f"ERROR: expected 30 seed documents, found {len(SEED_DOCUMENTS)}")
            sys.exit(1)

        for doc in SEED_DOCUMENTS:
            # Check if already seeded
            existing = await db.execute(
                text("SELECT id FROM document_chunks WHERE source_url = :src"),
                {"src": doc["source_url"]},
            )
            if existing.first():
                print(f"  Skipping (exists): {doc['source_url']}")
                skipped += 1
                continue

            print(f"  Embedding: {doc['source_url']} ...", end=" ", flush=True)
            try:
                result = await asyncio.to_thread(
                    genai.embed_content,
                    model="models/text-embedding-004",
                    content=doc["content"],
                    task_type="retrieval_document",
                )
                embedding = result["embedding"]
                emb_str = "[" + ",".join(str(x) for x in embedding) + "]"

                await db.execute(
                    text("""
                        INSERT INTO document_chunks (id, content, embedding, source_url)
                        VALUES (:id, :content, :emb::vector, :src)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "content": doc["content"],
                        "emb": emb_str,
                        "src": doc["source_url"],
                    },
                )
                await db.commit()
                seeded += 1
                print("done.")

                # Rate limit: ~3 per second to stay under 15 RPM
                await asyncio.sleep(0.4)

            except Exception as e:
                print(f"FAILED: {e}")
                await db.rollback()

        print(f"\nSeeded {seeded} new document chunks. Skipped {skipped} existing.")


if __name__ == "__main__":
    asyncio.run(seed())
