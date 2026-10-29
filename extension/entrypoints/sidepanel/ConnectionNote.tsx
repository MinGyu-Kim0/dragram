import { useEffect, useState } from "react";
import type { PatternConnection } from "@/utils/api";
import { fetchConnection } from "@/utils/connections";
import { createLimiter } from "@/utils/limiter";

const fills = createLimiter(2);

export function ConnectionNote({
  connection,
  pending,
}: {
  connection?: PatternConnection;
  pending: boolean;
}) {
  const [loaded, setLoaded] = useState<PatternConnection>();
  const id = connection?.pattern_id;
  const filled = connection?.filled;
  useEffect(() => {
    if (id === undefined || filled) return;
    let current = true;
    void fills
      .schedule(
        () => fetchConnection(id),
        () => !current,
      )
      .then(
        (result) => {
          if (current) setLoaded(result);
        },
        () => {
          /* 기존 카드는 유지하고, 다음에 카드를 열 때 다시 시도한다. */
        },
      );
    return () => {
      current = false;
    };
  }, [id, filled]);

  const result = filled
    ? connection
    : loaded?.pattern_id === id
      ? loaded
      : connection;
  if (!result?.text) return null;
  return (
    <p className="grammar-form">
      접속: {result.text}
      {!pending && result.review_status === "pending" && (
        <span className="badge-warn">AI 생성·미검수</span>
      )}
    </p>
  );
}
