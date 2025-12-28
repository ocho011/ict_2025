# 세션 연결 워크플로우 가이드

## 📤 기존 세션 종료 시 - 저장 워크플로우

### Step 1: 작업 상태 커밋
```bash
# Git 상태 확인
git status

# 변경사항 커밋 (필요시)
git add .
git commit -m "feat: [작업 내용]"
```

### Step 2: Serena MCP 메모리 저장
```bash
# MCP 툴 직접 호출
mcp__serena__write_memory("작업상태", "현재 진행 상황 설명...")
mcp__serena__write_memory("다음작업", "다음에 할 일 목록...")
```

**또는 자연어 명령**:
```
"현재 작업 상태를 메모리에 저장해줘"
"다음 작업 계획을 메모리에 저장해줘"
```

### Step 3: SuperClaude 세션 저장
```bash
# SuperClaude 세션 저장 명령
/sc:save
```

**자동 처리 내용**:
- Task Master 작업 상태 캡처
- Git 브랜치 및 커밋 정보 저장
- 세션 파일 생성 (`.taskmaster/sessions/`)
- 타임스탬프 포함 JSON 파일

### Step 4: 원격 저장소에 푸시
```bash
git push origin [브랜치명]
```

---

## 📥 신규 세션 시작 시 - 복원 워크플로우

### Step 1: Git 상태 확인
```bash
# 현재 브랜치 확인
git status
git branch

# 원격 최신 상태로 업데이트
git pull origin [브랜치명]
```

### Step 2: SuperClaude 세션 로드
```bash
# SuperClaude 세션 복원 명령
/sc:load
```

**자동 처리 내용**:
- 가장 최근 세션 파일 로드
- Git 브랜치 정보 복원
- Task Master 작업 상태 표시
- 컨텍스트 요약 제공

**또는 특정 세션 로드**:
```bash
/sc:load session-2025-12-28-151348.json
```

### Step 3: Serena MCP 메모리 확인
```bash
# 사용 가능한 메모리 목록 확인
mcp__serena__list_memories()

# 특정 메모리 읽기
mcp__serena__read_memory("작업상태")
mcp__serena__read_memory("다음작업")
```

**또는 자연어 명령**:
```
"메모리 목록 보여줘"
"작업상태 메모리 읽어줘"
"다음작업 메모리 읽어줘"
```

### Step 4: Task Master 작업 확인 (선택사항)
```bash
# 전체 작업 목록
task-master list

# 다음 작업 확인
task-master next

# 특정 작업 상세 보기
task-master show [task-id]
```

---

## 🔑 핵심 명령어 치트시트

### 세션 저장 (기존 세션 종료 시)

| 명령 타입 | 명령어 | 용도 |
|-----------|--------|------|
| **Git** | `git commit` | 코드 변경사항 저장 |
| **Git** | `git push` | 원격 저장소 동기화 |
| **SuperClaude** | `/sc:save` | 세션 상태 저장 |
| **Serena MCP** | `write_memory()` | 작업 컨텍스트 저장 |
| **자연어** | "세션 저장해줘" | 통합 저장 프로세스 |

### 세션 복원 (신규 세션 시작 시)

| 명령 타입 | 명령어 | 용도 |
|-----------|--------|------|
| **Git** | `git status` | 현재 상태 확인 |
| **Git** | `git pull` | 최신 코드 동기화 |
| **SuperClaude** | `/sc:load` | 세션 복원 |
| **Serena MCP** | `list_memories()` | 메모리 목록 확인 |
| **Serena MCP** | `read_memory()` | 저장된 컨텍스트 읽기 |
| **자연어** | "이전 세션 로드해줘" | 통합 복원 프로세스 |

---

## 📝 실전 예제

### 예제 1: 세션 종료 시

```bash
# 1. 현재 작업 커밋
git add .
git commit -m "feat: implement FVG detector"

# 2. Serena 메모리 저장
"FVG 구현 완료, 다음은 Order Block 구현 필요"라고 메모리에 저장해줘

# 3. SuperClaude 세션 저장
/sc:save

# 4. 푸시
git push origin feature/ict-indicators
```

### 예제 2: 세션 시작 시

```bash
# 1. Git 상태 확인
git status
git pull origin feature/ict-indicators

# 2. 세션 로드
/sc:load

# 3. 메모리 확인
메모리 목록 보여줘
작업상태 메모리 읽어줘

# 4. 다음 작업 시작
"다음 작업 뭐야?"
"Order Block 구현 시작하자"
```

---

## 🎯 권장 사항

### 세션 종료 시 체크리스트
- [ ] 모든 코드 변경사항 커밋됨
- [ ] Serena 메모리에 작업 상태 저장됨
- [ ] SuperClaude 세션 저장됨 (`/sc:save`)
- [ ] 원격 저장소에 푸시됨
- [ ] 다음 작업 계획 명확함

### 세션 시작 시 체크리스트
- [ ] Git 브랜치 확인 및 최신화
- [ ] SuperClaude 세션 로드됨 (`/sc:load`)
- [ ] Serena 메모리 확인됨
- [ ] 이전 작업 내용 파악됨
- [ ] 다음 작업 명확함

---

## 🔄 통합 워크플로우 다이어그램

```
세션 A (종료)
    │
    ├─ 1. git commit
    ├─ 2. write_memory() → Serena 메모리
    ├─ 3. /sc:save → 세션 파일
    ├─ 4. git push
    │
    ▼ (세션 종료)

    ▼ (신규 세션 시작)
    │
세션 B (시작)
    │
    ├─ 1. git status/pull
    ├─ 2. /sc:load ← 세션 파일
    ├─ 3. read_memory() ← Serena 메모리
    ├─ 4. task-master next (선택)
    │
    ▼ 작업 계속
```

---

## 💡 자주 사용하는 자연어 명령

### 저장 관련
- "세션 저장해줘"
- "현재 상태 저장해줘"
- "작업 내용 메모리에 저장해줘"
- "다음에 할 일 기록해줘"

### 복원 관련
- "이전 세션 로드해줘"
- "저장된 메모리 보여줘"
- "마지막 작업 뭐였어?"
- "다음에 뭐 해야 해?"

### 컨텍스트 확인
- "현재 브랜치 확인해줘"
- "메모리 목록 보여줘"
- "작업 상태 알려줘"
- "다음 작업 뭐야?"

---

## 📚 참고 파일 위치

### Serena MCP 메모리
```
.serena/memories/
├── mtf_implementation_status.md
├── ict_implementation_plan.md
└── [커스텀 메모리 파일들...]
```

### SuperClaude 세션
```
.taskmaster/sessions/
├── session-2025-12-28-151348.json
└── [세션 파일들...]
```

### Task Master
```
.taskmaster/tasks/
├── tasks.json
└── task-*.md
```

---

**마지막 업데이트**: 2025-12-28
**버전**: 1.0
