import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const distDir = path.join(projectRoot, "dist");
const publicDir = path.join(projectRoot, "public");
const assetsDir = path.join(distDir, "assets");

fs.rmSync(distDir, { recursive: true, force: true });
fs.mkdirSync(assetsDir, { recursive: true });

const apiBase = process.env.VITE_API_BASE_URL || "";
const envScript = `window.__BOLUS_API_BASE__ = ${JSON.stringify(apiBase)};`;
fs.writeFileSync(path.join(assetsDir, "env.js"), envScript, "utf8");

fs.copyFileSync(path.join(projectRoot, "index.html"), path.join(distDir, "index.html"));
fs.copyFileSync(path.join(projectRoot, "src", "main.js"), path.join(assetsDir, "main.js"));
fs.copyFileSync(path.join(projectRoot, "src", "style.css"), path.join(assetsDir, "style.css"));

if (fs.existsSync(publicDir)) {
  for (const entry of fs.readdirSync(publicDir)) {
    fs.copyFileSync(path.join(publicDir, entry), path.join(distDir, entry));
  }
}

console.log(`Build listo en ${distDir}`);
