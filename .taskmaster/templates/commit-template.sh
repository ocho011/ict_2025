#!/bin/bash
# Task 완료 후 문서화 및 커밋 자동화 스크립트
#
# 사용법:
#   ./commit-template.sh <task_id> "<task_title>"
#   예: ./commit-template.sh 1 "Project Foundation & Environment Setup"

set -e  # 에러 발생 시 스크립트 중단

# 인자 확인
if [ $# -lt 2 ]; then
    echo "Usage: $0 <task_id> \"<task_title>\""
    echo "Example: $0 1 \"Project Foundation & Environment Setup\""
    exit 1
fi

TASK_ID=$1
TASK_TITLE=$2
TASK_NAME=$(echo "$TASK_TITLE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -d '[:punct:]')
DOC_FILE=".taskmaster/docs/task-reports/task-${TASK_ID}-${TASK_NAME}.md"

echo "🚀 Task #${TASK_ID} 커밋 프로세스 시작..."

# 1. 문서 파일 존재 확인
if [ ! -f "$DOC_FILE" ]; then
    echo "❌ 오류: 문서 파일이 존재하지 않습니다: $DOC_FILE"
    echo "   템플릿으로 파일을 생성하세요:"
    echo "   cp .taskmaster/templates/task-report-template.md $DOC_FILE"
    exit 1
fi

echo "✅ 문서 파일 확인: $DOC_FILE"

# 2. Git 상태 확인
echo ""
echo "📊 현재 Git 상태:"
git status --short

# 3. 사용자 확인
echo ""
read -p "위 파일들을 커밋하시겠습니까? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 커밋 취소됨"
    exit 1
fi

# 4. 모든 변경사항 스테이징
echo ""
echo "📦 파일 스테이징 중..."
git add -A

# 5. 커밋 메시지 작성 및 커밋
echo ""
echo "💾 커밋 생성 중..."
git commit -m "feat: complete Task #${TASK_ID} - ${TASK_TITLE}

Implemented all subtasks for Task #${TASK_ID}

Closes: Task #${TASK_ID}
Refs: ${DOC_FILE}"

echo "✅ 커밋 완료!"

# 6. Task 상태 업데이트
echo ""
echo "🔄 Task Master 상태 업데이트 중..."
task-master set-status --id="${TASK_ID}" --status=done

# 7. Push 확인
echo ""
read -p "Git push를 실행하시겠습니까? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Push 중..."
    git push origin main
    echo "✅ Push 완료!"
else
    echo "ℹ️  Push는 나중에 수동으로 실행하세요: git push origin main"
fi

echo ""
echo "✨ Task #${TASK_ID} 완료 프로세스 종료!"
echo "📝 문서: $DOC_FILE"
