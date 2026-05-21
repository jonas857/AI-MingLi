# 八字命理分析系统 - Docker配置
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production
ENV FLASK_DEBUG=false

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
COPY pyproject.toml .

# 安装Python依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p local_data/bazi_data && \
    mkdir -p local_data/analysis_data && \
    mkdir -p local_data/sessions && \
    mkdir -p logs

# 设置权限
RUN chmod +x start-simplified-server.sh

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/status || exit 1

# 启动命令
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "300", "app_simplified:app"]

# 多阶段构建 - 开发版本
FROM python:3.11-slim as development

WORKDIR /app

# 安装开发依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir pytest pytest-cov black flake8 mypy

COPY . .

RUN mkdir -p local_data/bazi_data && \
    mkdir -p local_data/analysis_data && \
    mkdir -p local_data/sessions && \
    mkdir -p logs

EXPOSE 5000

# 开发环境启动命令
CMD ["python", "app_simplified.py"] 