export default function RootNotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-black p-6 text-white font-mono">
      <h1 className="text-2xl font-bold text-red-500">404 // ROOT_NOT_FOUND</h1>
      <a href="/en" className="border border-white px-4 py-2 hover:bg-white hover:text-black">
        [ OPEN /en ]
      </a>
    </div>
  );
}
