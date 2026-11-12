export function Hero() {
  return (
    <section className="py-24 text-center">
      <h1 className="text-5xl font-bold">
        The future of work is{" "}
        <span className={cn("bg-gradient-to-r from-pink-500 to-violet-600", "bg-clip-text text-transparent")}>
          AI-powered workflows
        </span>
      </h1>
    </section>
  );
}
