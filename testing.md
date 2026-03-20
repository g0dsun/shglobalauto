# 테스트 규칙

## 기본 원칙

- 전체 테스트 금지 → 관련 파일만 실행: `npm test -- --testPathPattern=<filename>`
- 새 함수/모듈 작성 시 유닛테스트 함께 작성
- 테스트 파일 위치: `__tests__/` 또는 소스 파일 옆 `*.test.ts`

## 테스트 작성 규칙

- describe → it 구조 사용
- 테스트명은 한국어로 작성 가능 (예: `it('빈 배열이면 에러를 던진다')`)
- mocking은 최소화, 실제 동작 테스트 우선
- edge case 반드시 포함: null, undefined, 빈 값, 경계값

## 워크플로우

1. 코드 수정
2. 타입체크: `npx tsc --noEmit`
3. 관련 테스트 실행
4. 린트: `npm run lint`
5. 모두 통과 후 완료 보고
