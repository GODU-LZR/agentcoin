'use client';

export default function NotFound() {
  return (
    <div className="flex h-screen flex-col items-center justify-center bg-black text-white font-mono gap-4">
      <h2 className="text-2xl text-red-500 font-bold">404 // NOT_FOUND</h2>
      <p>The requested subsystem interface could not be located.</p>
      <a href="/" className="px-4 py-2 border border-white hover:bg-white hover:text-black">
        [ RETURN_TO_ROOT ]
      </a>
    </div>
  );
}
