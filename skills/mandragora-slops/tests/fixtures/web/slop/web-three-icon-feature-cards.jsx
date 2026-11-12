import { Zap, Shield, Smile } from "lucide-react";

export default function Features() {
  return (
    <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
      <div className="rounded-xl border p-6">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-indigo-100">
          <Zap className="h-6 w-6 text-indigo-600" />
        </div>
        <h3 className="mt-4 font-semibold">Lightning fast</h3>
        <p className="mt-2 text-gray-600">Lorem ipsum dolor sit amet consectetur.</p>
      </div>
      <div className="rounded-xl border p-6">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-emerald-100">
          <Shield className="h-6 w-6 text-emerald-600" />
        </div>
        <h3 className="mt-4 font-semibold">Secure by design</h3>
        <p className="mt-2 text-gray-600">Lorem ipsum dolor sit amet consectetur.</p>
      </div>
      <div className="rounded-xl border p-6">
        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-amber-100">
          <Smile className="h-6 w-6 text-amber-600" />
        </div>
        <h3 className="mt-4 font-semibold">Easy to use</h3>
        <p className="mt-2 text-gray-600">Lorem ipsum dolor sit amet consectetur.</p>
      </div>
    </div>
  );
}
