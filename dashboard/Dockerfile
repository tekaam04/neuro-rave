FROM node:22-alpine

WORKDIR /app

# Install deps as a separate cached layer — only reruns when package.json changes
COPY package*.json ./
RUN npm install

# Source is volume-mounted at runtime so edits reflect instantly
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
