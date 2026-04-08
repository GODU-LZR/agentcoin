'use client';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex h-screen flex-col items-center justify-center bg-black text-white font-mono gap-4">
      <h2 className="text-xl text-red-500">Something went wrong!</h2>
      <pre className="bg-red-900/20 p-4 border border-red-500/50">{error.message}</pre>
      <button
        onClick={() => reset()}
        className="px-4 py-2 border border-white hover:bg-white hover:text-black"
      >
        Try again
      </button>
    </div>
  );
}
