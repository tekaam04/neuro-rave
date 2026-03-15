import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Maps @config → config/ at the project root.
      // In Docker the volume is mounted at /app/config.
      '@config': path.resolve(__dirname, '../config'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
})
