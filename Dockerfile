FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Rebuild sample data from source and prove the golden set against it at build time.
RUN python -m tools.build_sample_corpus \
 && python -m tools.build_sample_questionnaires \
 && python -m evals.validate_golden_set

# Default: offline test suite. Override to run the agent, e.g.
#   docker compose run agent python -m evals.run_evals data/sample/questionnaires/northgate_rfp.docx
CMD ["pytest", "-q"]
