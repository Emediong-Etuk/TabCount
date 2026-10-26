# Multi-arch: builds natively on arm64 (AWS Graviton) and amd64.
# Official python:3.12-slim image, pulled from the AWS ECR Public mirror (no Docker Hub rate limits).
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -c "import cv2; assert cv2.__version__.startswith('5'), cv2.__version__; print('OpenCV', cv2.__version__)"

COPY app/ ./app/

RUN useradd --create-home --uid 10001 tabcount
USER tabcount

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# --no-access-log keeps client IP addresses out of the logs.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
