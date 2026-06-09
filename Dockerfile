FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（playwright 等爬虫工具需要，暂时跳过）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" && \
    pip install --no-cache-dir streamlit

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p outputs traces artifacts

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "src/api/routes.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true"]
