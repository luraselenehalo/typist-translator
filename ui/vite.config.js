import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Everything is inlined into one index.html so pywebview can load it straight
// from disk: Chromium blocks ES module imports over file://, and a single
// self-contained document sidesteps that without running a local web server.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsInlineLimit: 100000000,
    cssCodeSplit: false,
    reportCompressedSize: false,
    target: 'chrome110',
  },
})
