# 로컬 개발 서버용. 운영은 빌드 결과(dist)를 Caddy가 제공하므로 이 이미지를 쓰지 않는다(infra/deploy.sh).
FROM node:22-alpine
WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
