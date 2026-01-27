# LARS Dashboard Micro-App
# Build: docker build -t my-dashboard .
# Run:   docker run -p 15400:15400 -e LARS_URL=postgresql://host:15432/default my-dashboard

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY app.py .
COPY static/ static/

# Expose port
EXPOSE 15400

# Run the app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "15400"]
