'use client';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="bg-black text-white font-mono">
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6">
          <h1 className="text-xl font-bold text-red-500">GLOBAL_ERROR</h1>
          <pre className="max-w-3xl overflow-auto border border-red-500/40 bg-red-950/30 p-4 text-sm">
            {error.message || 'Unexpected application failure'}
          </pre>
          <button
            onClick={() => reset()}
            className="border border-white px-4 py-2 hover:bg-white hover:text-black"
          >
            Retry
          </button>
        </div>
      </body>
    </html>
  );
}
