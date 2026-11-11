// 이 컨테이너의 localhost:<포트>를 compose 서비스로 잇는다. 사용: node forward.mjs <포트> <서비스>
// 확장 개발 빌드와 웹은 API를 localhost:8000, 웹을 localhost:5173으로 보므로(기본값) 그대로 쓴다.
import net from "node:net";

const [port, host] = [Number(process.argv[2]), process.argv[3]];
net
  .createServer((client) => {
    const server = net.connect(port, host);
    client.pipe(server).pipe(client);
    client.on("error", () => server.destroy());
    server.on("error", () => client.destroy());
  })
  .listen(port);
