# 使用轻量级 Python 镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 安装必要的系统依赖（如果需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件（可选，如果有 requirements.txt）
# 暂时直接安装
RUN pip install --no-cache-dir \
    fastmcp \
    tavily-python \
    httpx \
    watchdog \
    python-dotenv

# 复制源代码
COPY . .

# 暴露端口（MCP 主要是 StdIO，但也支持 HTTP）
EXPOSE 8000

# 默认启动命令
# 注意：使用 -u 禁用 Python 输出缓冲，确保日志实时
CMD ["python", "-u", "app/main.py"]
