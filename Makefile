.PHONY: up down db dev

up:
	docker compose up -d --build

down:
	docker compose down

db:
	docker compose up -d redis qdrant

dev: db
	python main.py
