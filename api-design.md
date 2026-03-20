# API 설계 규칙

## 네이밍

- URL: kebab-case (`/user-profiles`)
- 쿼리 파라미터: camelCase (`?pageSize=10`)
- JSON 필드: camelCase (`{ "userName": "..." }`)

## RESTful 규칙

| 메서드 | 용도 | 예시 |
|--------|------|------|
| GET | 조회 | `GET /api/users/:id` |
| POST | 생성 | `POST /api/users` |
| PUT | 전체 수정 | `PUT /api/users/:id` |
| PATCH | 부분 수정 | `PATCH /api/users/:id` |
| DELETE | 삭제 | `DELETE /api/users/:id` |

## 응답 형식

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": { "page": 1, "totalPages": 5 }
}
```

## 에러 처리

- HTTP 상태코드 정확히 사용 (200, 201, 400, 401, 403, 404, 500)
- 에러 응답에 `code`, `message` 필수 포함
- 유효성 검증 에러는 필드별로 분리

## 설계 원칙

- 페이지네이션 기본 적용 (목록 API)
- 버전 관리: URL prefix (`/api/v1/`)
- 인증 필요 엔드포인트 명시
