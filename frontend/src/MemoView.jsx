import { marked } from "marked";

export default function MemoView({ memo }) {
  const download = () => {
    const blob = new Blob([memo], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "investment-memo.md";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <section className="memo">
      <div className="memo-head">
        <h2>📋 Investment Memo</h2>
        <button onClick={download}>Download .md</button>
      </div>
      <div className="memo-body" dangerouslySetInnerHTML={{ __html: marked.parse(memo) }} />
    </section>
  );
}
