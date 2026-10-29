import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals를 켜지 않아 Testing Library가 자동 정리를 등록하지 못하므로 직접 등록한다.
afterEach(cleanup);
