up:
	docker compose up --build || docker container rm -f $$(docker ps -aq)

down:
	docker compose down --volumes

restart: down up

status:
	docker compose ps -a