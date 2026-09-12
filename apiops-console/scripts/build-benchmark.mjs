import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { build } from 'vite'

// Build the viewer and its actual imports independently of unrelated Console pages.
await build({
  configFile: false,
  plugins: [react()],
  build: {
    outDir: 'dist/benchmark',
    lib: {
      entry: fileURLToPath(new URL('../src/features/benchmark/BenchmarkPage.tsx', import.meta.url)),
      formats: ['es'],
      fileName: 'benchmark',
    },
    rollupOptions: { external: ['react', 'react-dom', 'react/jsx-runtime'] },
  },
})
