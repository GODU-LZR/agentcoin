FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md README.zh-CN.md README.ja.md ./
COPY agentcoin ./agentcoin
COPY configs ./configs

RUN python -m pip install --no-cache-dir .

EXPOSE 8080

CMD ["agentcoin-node", "--config", "configs/node.example.json"]

