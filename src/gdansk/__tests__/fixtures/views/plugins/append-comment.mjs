export default function (options) {
  return [
    {
      name: "append-comment",
      async build({ files, readFile, writeFile }) {
        for (const file of files) {
          const original = await readFile(file);
          await writeFile(file, `${original}\n/* ${options.comment} */\n`);
        }
      },
    },
  ];
}
