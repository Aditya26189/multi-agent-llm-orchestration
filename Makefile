.PHONY: up down seed test eval logs

up:
	docker compose up --build --wait

down:
	docker compose down -v

seed:
	docker compose run --rm api alembic upgrade head
	docker compose run --rm api python scripts/seed_kb.py

test:
	docker compose exec api pytest tests/ -v --tb=short

eval:
	docker compose exec api python -c "import asyncio; from eval.harness import EvaluationHarness; asyncio.run(EvaluationHarness().run_all())"

logs:
	docker compose logs -f --tail=100
