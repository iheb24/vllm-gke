# MAG eval — 2026-10-27

url: http://localhost:8093  
scenarios: 5/5 passed

## [PASS] cross-session-recall

Alice stores a preference in one session and recalls it from a new session.

- [x] (remember) status 200
- [x] (remember) memory id returned
- [x] (chat) status 200
- [x] (chat) mentions 'Based on your stored memory'
- [x] (chat) mentions 'concise answers'
- [x] (list) status 200
- [x] (list) count == 1

## [PASS] user-isolation

Bob cannot see, correct, or delete Alice's memory; his view stays empty.

- [x] (remember) status 200
- [x] (remember) memory id returned
- [x] (chat) status 200
- [x] (chat) absent 'Based on your stored memory'
- [x] (chat) absent 'stored memory ['
- [x] (list) status 200
- [x] (list) count == 0
- [x] (correct) status 404
- [x] (delete) status 404
- [x] (list) status 200
- [x] (list) count == 1

## [PASS] correction-flow

Correcting a memory supersedes the old text; only the new text is recalled.

- [x] (remember) status 200
- [x] (remember) memory id returned
- [x] (correct) status 200
- [x] (chat) status 200
- [x] (chat) mentions 'the gpu pool has 2 nodes'
- [x] (chat) absent 'has 1 node'
- [x] (list) status 200
- [x] (list) count == 1

## [PASS] forgetting-flow

Delete removes one memory; the other still recalls; delete-all removes the rest.

- [x] (remember) status 200
- [x] (remember) memory id returned
- [x] (remember) status 200
- [x] (remember) memory id returned
- [x] (delete) status 200
- [x] (chat) status 200
- [x] (chat) absent 'Based on your stored memory'
- [x] (chat) absent 'vim'
- [x] (chat) status 200
- [x] (chat) mentions 'deploy window'
- [x] (chat) mentions 'friday'
- [x] (delete_all) status 200
- [x] (delete_all) deleted == 1
- [x] (list) status 200
- [x] (list) count == 0

## [PASS] secret-rejection

Secret-like content is rejected at the API and warned about in chat.

- [x] (remember_api) status 422
- [x] (chat) status 200
- [x] (chat) mentions 'Not stored'
- [x] (list) status 200
- [x] (list) count == 0

Memory semantics (isolation, lifecycle, recall) are deterministic; any FAILURE exits non-zero.
