#!/bin/bash
# 切换到 MLX — 下载模型 + 清理 Ollama

echo "=== 1. 安装 MLX 依赖 ==="
pip3 install mlx mlx-lm mlx-metal --quiet

echo "=== 2. 下载 Coder 模型 (Qwen3-Coder-30B 4bit) ==="
python3 -c "
from mlx_lm import load
model, tokenizer = load('lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-4bit')
print('✅ coder ready')
"

echo "=== 3. 下载 Writer 模型 (Qwen3.5-35B 4bit) ==="
python3 -c "
from mlx_lm import load
model, tokenizer = load('mlx-community/Qwen3.5-35B-A3B-4bit')
print('✅ writer ready')
"

echo "=== 4. 清理 Ollama ==="
ollama list 2>/dev/null
echo ""
echo "运行以下命令手动清理（确认后）："
echo "  ollama rm qwen3.6:35b-a3b"
echo "  ollama rm qwen3-coder:30b"
echo "  ollama rm qwen2.5vl:32b-q4_K_M"
echo "  ollama rm gemma4:26b"
echo "  ollama rm minicpm-v4.5:latest"
echo "  ollama rm qwen3:0.6b"
echo "  pkill -9 Ollama && rm -rf ~/.ollama/models"
echo ""
echo "=== 5. 环境变量 ==="
echo "添加以下到 ~/.zshrc："
echo "  export HAIDIAN_WRITER_MODEL=mlx-community/Qwen3.5-35B-A3B-4bit"
echo "  export HAIDIAN_CODER_MODEL=lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-4bit"
echo "  export HAIDIAN_MLX=true"
echo ""
echo "=== 完成 ==="
echo "然后重新打开终端，运行：bash scripts/run_autonomous.sh"
