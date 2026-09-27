# Minji AI (Samantha-AI) 프로젝트 규칙 및 배포 자동화 가이드

이 문서는 `minji_AI` 프로젝트의 개발 및 배포 표준 작업 절차(SOP)를 정의합니다.
사용자가 코드 수정 또는 기능 개선을 요청할 경우, 에이전트(Antigravity)는 항상 다음 프로세스를 순차적이고 완전하게 자동 수행해야 합니다.

---

## 1. 인프라 및 환경 정보
- **GitHub Repository**: `https://github.com/kangsubsong76-droid/minji_AI.git` (main 브랜치)
- **EC2 SSH Host**: `samantha-ec2` (로컬 `~/.ssh/config` 기반)
- **EC2 프로젝트 경로**: `~/samantha-ai/samantha-ai`
- **Docker 컨테이너명**: `samantha-app` (이미지: `samantha-backend`, 포트: `80:8000`)
- **서비스 URL**: `http://<EC2_PUBLIC_IP>/`

---

## 2. 표준 배포 파이프라인 (작업 시 자동 수행)

사용자가 기능 추가, 버그 수정, UI 변경 등을 요청할 때 반드시 아래 **3단계 파이프라인**을 한 턴 내에 중단 없이 완료합니다.

### [Phase 1] 로컬 코드 작성 및 자체 검증
1. 로컬 작업 공간에서 요구사항에 맞는 코드 작성 및 수정 (`main.py`, `requirements.txt`, `Dockerfile` 등).
2. 파이썬 문법 검사 및 필수 종속성 확인.

### [Phase 2] Git Commit & Remote Push
1. 변경 사항 스테이징:
   ```bash
   git add .
   ```
2. 의미 있는 커밋 메시지로 커밋:
   ```bash
   git commit -m "feat/fix: <상세 작업 내용>"
   ```
3. GitHub `main` 브랜치로 푸시:
   ```bash
   git push origin main
   ```

### [Phase 3] EC2 원격 SSH 빌드 및 무중단 배포
1. 로컬에서 `ssh samantha-ec2`를 통해 다음 원격 배포 명령어를 즉시 실행:
   ```bash
   ssh samantha-ec2 "cd ~/samantha-ai/samantha-ai && git pull && sudo docker build -t samantha-backend . && sudo docker rm -f samantha-app 2>/dev/null && sudo docker run -d --name samantha-app --restart always -p 80:8000 samantha-backend"
   ```
2. 컨테이너 구동 상태 확인:
   ```bash
   ssh samantha-ec2 "sudo docker ps --filter name=samantha-app && sudo docker logs --tail 20 samantha-app"
   ```

---

## 3. 핵심 시스템 아키텍처 및 요구 기능 사양

### (1) 대화 장기 기억 (Memory)
- 세션 ID(`session_id`) 기반의 대화 히스토리 관리.
- 사용자와 민지의 대화 기록 및 비전(Vision) 분석 내역을 세션 컨텍스트에 지속적으로 유지하여 이전 대화 맥락을 기억하고 연결.
- 필요 시 대화 세션을 리셋할 수 있는 초기화 기능 지원.

### (2) 사용자 발화 중단 (Barge-in / Interrupt)
- 민지가 오디오를 재생하는 도중(`isSpeaking == true`):
  - 사용자가 마이크를 통해 말을 시작하거나 소리를 낼 때,
  - 또는 오라클 구체 / 마이크 토글 버튼 조작 시,
  - 즉시 재생 중단 (`audioPlayer.pause()`, `audioPlayer.currentTime = 0`), 오라클 구체를 경청 상태(`listening`)로 전환하고 사용자 음성 수신으로 즉각 복귀.

### (3) 카메라 시각 인지 (Vision)
- 실시간 카메라 프레임을 캡처하여 Gemini 2.5 Flash 모델로 전송.
- 영화 'Her' 사만다의 톤앤매너(다정하고 자연스러운 반말, 1~2문장)로 즉시 시각적 피드백 제공.
- 분석 결과는 세션 메모리에도 동기화되어 이후 대화에서 언급 가능.

### (4) 오라클 구체 애니메이션 Visualizer
- **대기/휴식 (Idle)**: 부드러운 웜 오렌지/레드 호흡 펄스
- **듣는 중 (Listening)**: 네온 블루/시안 그라디언트 + 반응형 펄스
- **생각 중 (Thinking)**: 미스틱 퍼플/핑크 그라디언트 회전
- **말하는 중 (Speaking)**: 앰버/코랄 그라디언트 + 다이내믹 사운드 웨이브 펄스
- **음소거 (Muted)**: 딥 그레이 톤 및 정적 상태
