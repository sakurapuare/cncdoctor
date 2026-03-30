# API Reference

All endpoints return the same envelope:

```json
{
  "code": 0,
  "msg": "成功",
  "data": {}
}
```

## `GET|POST /health`

Returns runtime status, enabled features, active classifier backend, and case count.

## `GET|POST /docs`

Returns the endpoint catalog and response contract.

## `GET|POST /qa`

Parameters:

- `pinpai`
- `xinghao`
- `errorid`
- `question`
- `relationList`

Purpose:

- Diagnose a CNC fault from free text and optional structured hints.

## `GET|POST /pa`

Parameters:

- `pinpai`
- `xinghao`
- `errorid`
- `question`
- `relationList`

Purpose:

- Perform online analysis with fallback to the local case base.

## `GET|POST /save`

Parameters:

- `pinpai`
- `xinghao`
- `errorid`
- `question`
- `selectedList`
- `yuanyin`
- `answer`

Purpose:

- Persist user feedback into the local case base and optionally Neo4j.

## `GET|POST /buquan`

Parameters:

- `question_start`

Purpose:

- Return autocomplete suggestions from local cases and graph descriptions.

## `GET|POST /wenda`

Parameters:

- `question`

Purpose:

- Answer structured maintenance questions from graph data or case retrieval.
