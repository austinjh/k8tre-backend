FROM python:3.14-slim
WORKDIR /app
COPY main.py lifecycle_client.py lifecycle_roles.py lifecycle_routes.py requirements.txt ./
COPY templates ./templates
COPY static ./static
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
