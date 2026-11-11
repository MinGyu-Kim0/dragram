import pg from "pg";

// 운영자가 확인할 수 있는 바깥 결과(사용 기록 등)를 E2E 스택 DB에서 읽는다(e2e/compose.yaml).
export async function query<T extends pg.QueryResultRow>(
  sql: string,
  params: unknown[] = [],
): Promise<T[]> {
  const client = new pg.Client({
    connectionString: process.env.E2E_DATABASE_URL,
  });
  await client.connect();
  try {
    return (await client.query<T>(sql, params)).rows;
  } finally {
    await client.end();
  }
}

// 문장 분석에 부른 LLM 호출 수(FR-A18 사용 기록). 패턴 단위로 공용 지식을 채우는 호출(접속 형태,
// 용법 빈 칸)은 패널이 결과를 보인 뒤 따로 부르므로 세지 않는다.
export async function analysisLlmCalls(): Promise<number> {
  const [row] = await query<{ count: string }>(
    `select count(*) from usage_log
     where kind = 'llm' and purpose not in ('pattern_connection', 'usage_fill')`,
  );
  return Number(row.count);
}

// dev-login 계정의 분석 요청이 지난 경로(cache·db·llm), 요청 순서대로.
export async function requestPaths(email: string): Promise<string[]> {
  const rows = await query<{ path: string }>(
    `select l.path from usage_log l join accounts_user u on u.id = l.user_id
     where l.kind = 'request' and u.username = $1 order by l.id`,
    [`dev:${email}`],
  );
  return rows.map((row) => row.path);
}
