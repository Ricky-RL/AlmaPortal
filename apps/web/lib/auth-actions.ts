"use server";

import { redirect } from "next/navigation";
import { createSupabaseServerClient } from "@/lib/supabase/server";

export async function signOutReviewer(): Promise<string | undefined> {
  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.signOut({ scope: "local" });
  if (error) {
    return "Sign out could not be completed. Please try again.";
  }
  redirect("/login");
}
