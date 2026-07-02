FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY wechat_skill_distill ./wechat_skill_distill

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "wechat_skill_distill.cli", "chat-ui", "--host", "0.0.0.0"]
