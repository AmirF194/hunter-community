#!/usr/bin/env bash
# 从 v1.0.x 升级到 v1.1.x 时,把两个原来 bind mount 的目录搬进新的具名卷。
#
# ## 为什么需要这一步
#
# v1.0.x 的 docker-compose.yml 把仓库目录直接挂给 api:
#     ./user-skills    → /opt/hunter-user-skills   (你在界面里装的 SKILL)
#     ./data-packages  → /opt/hunter-packages      (导入/导出的数据包)
# v1.1.0 起这两处改成 api 自己的具名卷(`hunter_user_skills` / `hunter_packages`)——
# 云平台上没有仓库目录,挂不了。
#
# 后果:直接升级的话,**新卷是空的**,你装过的 SKILL 会从界面上消失。
# 文件一个都没丢(还在 ./user-skills/ 下),只是容器看不到了。
# 这个脚本就是把它们搬过去。
#
# ## 用法(在部署目录执行,不需要停服务)
#
#     bash scripts/migrate-volumes.sh            # 真搬
#     bash scripts/migrate-volumes.sh --dry-run  # 只看会搬什么
#
# 幂等:目标卷非空时跳过,不覆盖已有内容。搬完在界面「能力库」里确认一下。
set -euo pipefail

DRY=0
PROJECT=""

# compose 的项目名决定卷的前缀。优先级:命令行 --project > COMPOSE_PROJECT_NAME
# > 问 compose 自己(它读 docker-compose.yml 里的 `name: hunter-community`)。
#
# ⚠️ `docker compose -p <名> up` 起的栈,这个脚本是**问不出来**那个名字的 ——
#    -p 只活在那一条命令里,不落任何文件。M4 实测:那种部署跑本脚本会拿到
#    hunter-community,然后报「卷还不存在」,提示把人往「先 up -d」的方向带偏。
#    所以下面卷找不到时会把疑似的卷名列出来。
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)   DRY=1 ;;
        --project)   PROJECT="${2:?--project 后面要跟项目名}"; shift ;;
        --project=*) PROJECT="${1#--project=}" ;;
        -h|--help)   echo "用法:bash scripts/migrate-volumes.sh [--dry-run] [--project <compose项目名>]"; exit 0 ;;
        *)           echo "不认识的参数:$1(--help 看用法)" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$PROJECT" ] || PROJECT="${COMPOSE_PROJECT_NAME:-}"
if [ -z "$PROJECT" ]; then
    PROJECT="$(docker compose config --format json 2>/dev/null \
                | python3 -c 'import json,sys;print(json.load(sys.stdin).get("name",""))' 2>/dev/null || true)"
fi
PROJECT="${PROJECT:-hunter-community}"
echo "compose 项目名:$PROJECT（不对的话:bash scripts/migrate-volumes.sh --project <你的项目名>）"

migrate_one() {
    local src="$1" vol="${PROJECT}_$2" label="$3"

    if [ ! -d "$src" ]; then
        echo "⏭  $label:本地没有 $src/,跳过"
        return
    fi
    # 只数真正的内容:README.md 这种随仓库走的文件不算
    local n
    n=$(find "$src" -mindepth 1 -maxdepth 1 ! -name 'README.md' ! -name '.gitkeep' 2>/dev/null | wc -l)
    if [ "$n" -eq 0 ]; then
        echo "⏭  $label:$src/ 里没有内容,跳过"
        return
    fi

    if ! docker volume inspect "$vol" >/dev/null 2>&1; then
        echo "⏭  $label:卷 $vol 还不存在"
        local guess
        guess=$(docker volume ls --format '{{.Name}}' | grep -E "_$2\$" | head -5)
        if [ -n "$guess" ]; then
            echo "    但机器上有这些同名后缀的卷 —— 项目名多半不是 $PROJECT:"
            echo "$guess" | sed 's/^/      /'
            echo "    重跑:bash scripts/migrate-volumes.sh --project <上面卷名里 _$2 之前那一段>"
        else
            echo "    先 docker compose up -d 把卷建出来再跑本脚本"
        fi
        return
    fi

    local existing
    existing=$(docker run --rm -v "$vol":/dst alpine sh -c 'ls -A /dst 2>/dev/null | wc -l')
    if [ "$existing" -gt 0 ]; then
        echo "⏭  $label:卷 $vol 已有 $existing 项内容,跳过(不覆盖)"
        return
    fi

    echo "→  $label:$src/($n 项)→ 卷 $vol"
    if [ "$DRY" = 1 ]; then
        find "$src" -mindepth 1 -maxdepth 1 ! -name 'README.md' -printf '     %f\n' 2>/dev/null | head -20
        return
    fi
    docker run --rm -v "$PWD/$src":/src:ro -v "$vol":/dst alpine \
        sh -c 'cp -a /src/. /dst/ && ls -A /dst | wc -l' \
        | sed 's/^/   搬进去 /;s/$/ 项/'
    echo "✅ $label 完成"
}

migrate_one user-skills   hunter_user_skills "用户 SKILL"
migrate_one data-packages hunter_packages    "数据包"

echo
echo "搬完之后重启这两个容器,让它们重新扫一遍 SKILL(对话数据不受影响):"
echo "    docker compose restart api opencode"
echo
echo "（原来这里印的是直接 curl opencode 的 /skill/refresh —— 那条命令在开了"
echo "  OPENCODE_PASS 的部署上会 401,而 curl -s 把 401 的响应体也吞掉了,"
echo "  看上去像是成功了。重启 opencode 时它会自己按 skills.urls 重新拉一遍,更稳。）"
