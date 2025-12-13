import { defineConfig } from 'vite';

export default defineConfig({
    build: {
        outDir: 'dist',
        assetsDir: 'assets',
        // Ensure we don't have separate files for lib/api
        rollupOptions: {
            output: {
                entryFileNames: 'assets/[name]-[hash].js',
                chunkFileNames: 'assets/[name]-[hash].js',
                assetFileNames: 'assets/[name]-[hash].[ext]'
            }
        }
    },
    server: {
        proxy: {
            '/api': {
                target: 'http://localhost:8000', // Adjust backend port if needed, assuming default Python/FastAPI
                changeOrigin: true
            }
        }
    }
});
