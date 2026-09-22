FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Rebuild the sample KB PDFs from source so the image is self-consistent,
# then validate the golden eval set against them at build time.
RUN python -m tools.build_sample_corpus && python -m evals.validate_golden_set

# Phase 0 default: run the test suite. Later phases switch this to the API/UI.
CMD ["pytest", "-q"]
