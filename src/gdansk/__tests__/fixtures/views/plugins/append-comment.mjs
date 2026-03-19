export default function (options) {
  return {
    name: "append-comment",
    apply: "build",
    transform: {
      filter: {
        id: {
          include: [/\.css$/],
        },
      },
      async handler(source, id) {
        if (!id.endsWith(".css")) {
          return source;
        }

        return `${source}\n/* ${options.comment} */\n`;
      },
    },
  };
}
