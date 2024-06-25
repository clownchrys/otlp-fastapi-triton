FROM python:3.11-slim

COPY ./requirements.txt ./
RUN pip install -r requirements.txt

WORKDIR /app
EXPOSE 8000
CMD python main.py
