import fs from "node:fs/promises";
export default function (options) {
  return {
    name: "watch-comment",
    apply: "build",
    transform: {
      filter: { id: { include: [/\.css$/] } },
      async handler(source, id) {
        if (!id.endsWith(".css")) return source;
        this.addWatchFile(options.watchFile);
        const comment = (await fs.readFile(options.watchFile, "utf8")).trim();
        return `${source}
/* ${comment} */
`;
      },
    },
  };
}
