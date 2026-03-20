# 보안 체크리스트

## 코드 작성 시 필수 확인

- [ ] 사용자 입력 검증 (서버 사이드 필수)
- [ ] SQL Injection 방지 (parameterized query 사용)
- [ ] XSS 방지 (출력 이스케이프)
- [ ] CSRF 토큰 적용
- [ ] 민감 정보 하드코딩 금지 (환경변수 사용)

## 인증 & 인가

- JWT 토큰 만료시간 설정 필수
- refresh token은 httpOnly cookie에 저장
- 비밀번호: bcrypt 해싱 (최소 salt rounds 10)
- API 키는 `.env`에만 저장, `.gitignore`에 반드시 포함

## 데이터

- 개인정보 로깅 금지
- DB 쿼리에 LIMIT 필수 (대량 조회 방지)
- 파일 업로드 시 확장자/MIME 타입 검증

## 의존성

- `npm audit` 정기 실행
- 알려진 취약 패키지 사용 금지
- 최소 권한 원칙 적용
