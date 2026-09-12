"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, FileCheck, FileUp } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, Card, FieldError, Input, Textarea } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  ACCEPTED_RESUME_EXTENSIONS,
  MAX_RESUME_BYTES,
  type PublicUploader,
  UploadError,
  uploadPublicLead,
} from "@/lib/public-upload";

const resumeSchema = z
  .custom<FileList>((value) => value instanceof FileList, {
    message: "Choose a resume or CV.",
  })
  .refine((files) => files?.length === 1, "Choose one resume or CV.")
  .refine(
    (files) => !files?.[0] || files[0].size > 0,
    "The file cannot be empty.",
  )
  .refine(
    (files) => !files?.[0] || files[0].size <= MAX_RESUME_BYTES,
    "The file must be no larger than 10 MiB.",
  )
  .refine((files) => {
    const file = files?.[0];
    if (!file) return true;
    const name = file.name.toLowerCase();
    return ACCEPTED_RESUME_EXTENSIONS.some((extension) =>
      name.endsWith(extension),
    );
  }, "Use a PDF, DOC, or DOCX file.");

export const MAX_COMMENTS_LENGTH = 2000;

export const leadFormSchema = z.object({
  firstName: z.string().trim().min(1, "Enter a first name.").max(100),
  lastName: z.string().trim().min(1, "Enter a last name.").max(100),
  email: z.string().trim().email("Enter a valid email address.").max(320),
  comments: z
    .string()
    .max(
      MAX_COMMENTS_LENGTH,
      `Comments must be at most ${MAX_COMMENTS_LENGTH} characters.`,
    ),
  resume: resumeSchema,
  acknowledgement: z
    .boolean()
    .refine(
      (checked) => checked,
      "Confirm that every field and the uploaded file use synthetic data.",
    ),
});

type LeadFormValues = z.infer<typeof leadFormSchema>;

function formatResumeSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function LeadForm({
  uploader = uploadPublicLead,
}: {
  uploader?: PublicUploader;
}) {
  const [progress, setProgress] = useState(0);
  const [submissionError, setSubmissionError] = useState<string>();
  const [submitted, setSubmitted] = useState(false);
  const [selectedResume, setSelectedResume] = useState<File>();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LeadFormValues>({
    resolver: zodResolver(leadFormSchema),
    defaultValues: {
      firstName: "",
      lastName: "",
      email: "",
      comments: "",
      acknowledgement: false,
    },
  });
  const resumeField = register("resume");

  const submit = handleSubmit(async (values) => {
    setSubmissionError(undefined);
    setProgress(0);
    try {
      const comments = values.comments.trim();
      await uploader(
        {
          firstName: values.firstName.trim(),
          lastName: values.lastName.trim(),
          email: values.email.trim(),
          resume: values.resume[0],
          syntheticDataAcknowledged: true,
          ...(comments ? { comments } : {}),
        },
        setProgress,
      );
      setSubmitted(true);
    } catch (error) {
      setSubmissionError(
        error instanceof UploadError || error instanceof Error
          ? error.message
          : "We could not submit the form. Please try again.",
      );
    }
  });

  if (submitted) {
    return (
      <Card className="flex min-h-80 flex-col items-center justify-center text-center">
        <CheckCircle2
          className="mb-5 size-12 text-[var(--green)]"
          aria-hidden="true"
        />
        <h2 className="text-2xl font-bold">Submission received</h2>
        <p className="mt-3 max-w-md text-[var(--muted)]">
          Thank you. Your synthetic assessment submission has been received.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <form noValidate onSubmit={submit} aria-busy={isSubmitting}>
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="block font-semibold">
            First name
            <Input
              className="mt-2"
              autoComplete="given-name"
              aria-invalid={Boolean(errors.firstName)}
              aria-describedby={
                errors.firstName ? "first-name-error" : undefined
              }
              disabled={isSubmitting}
              {...register("firstName")}
            />
            <FieldError
              id="first-name-error"
              message={errors.firstName?.message}
            />
          </label>
          <label className="block font-semibold">
            Last name
            <Input
              className="mt-2"
              autoComplete="family-name"
              aria-invalid={Boolean(errors.lastName)}
              aria-describedby={errors.lastName ? "last-name-error" : undefined}
              disabled={isSubmitting}
              {...register("lastName")}
            />
            <FieldError
              id="last-name-error"
              message={errors.lastName?.message}
            />
          </label>
        </div>

        <label className="mt-5 block font-semibold">
          Email
          <Input
            className="mt-2"
            type="email"
            autoComplete="email"
            inputMode="email"
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? "email-error" : undefined}
            disabled={isSubmitting}
            {...register("email")}
          />
          <FieldError id="email-error" message={errors.email?.message} />
        </label>

        <div className="mt-5">
          <label className="block font-semibold" htmlFor="comments">
            Comments{" "}
            <span className="font-normal text-[var(--muted)]">(optional)</span>
          </label>
          <span
            id="comments-instructions"
            className="mt-1 block text-sm font-normal text-[var(--muted)]"
          >
            Add any additional notes for reviewers. Maximum 2,000 characters.
          </span>
          <Textarea
            id="comments"
            className="mt-2"
            rows={4}
            maxLength={MAX_COMMENTS_LENGTH}
            aria-invalid={Boolean(errors.comments)}
            aria-describedby={
              errors.comments
                ? "comments-instructions comments-error"
                : "comments-instructions"
            }
            disabled={isSubmitting}
            {...register("comments")}
          />
          <FieldError id="comments-error" message={errors.comments?.message} />
        </div>

        <div className="relative mt-5">
          <input
            id="resume"
            className="peer sr-only"
            type="file"
            accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            aria-invalid={Boolean(errors.resume)}
            aria-describedby={
              errors.resume
                ? "resume-instructions resume-error"
                : "resume-instructions"
            }
            disabled={isSubmitting}
            {...resumeField}
            onChange={(event) => {
              void resumeField.onChange(event);
              setSelectedResume(event.currentTarget.files?.[0]);
            }}
          />
          <label
            className="block font-semibold peer-focus-visible:rounded-2xl peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--coral)]"
            htmlFor="resume"
          >
            Resume or CV
            <span
              id="resume-instructions"
              className="mt-1 block text-sm font-normal text-[var(--muted)]"
            >
              One PDF, DOC, or DOCX file. Maximum 10 MiB.
            </span>
            <span
              className={cn(
                "mt-2 flex min-h-28 cursor-pointer flex-col items-center justify-center rounded-2xl border border-[var(--green)] px-4 text-center",
                selectedResume
                  ? "border-solid bg-[var(--cream)]"
                  : "border-dashed bg-white hover:bg-[var(--cream)]",
              )}
            >
              {selectedResume ? (
                <FileCheck className="mb-2 size-6" aria-hidden="true" />
              ) : (
                <FileUp className="mb-2 size-6" aria-hidden="true" />
              )}
              {selectedResume ? (
                <>
                  <span className="max-w-full break-all text-sm font-semibold">
                    {selectedResume.name}
                  </span>
                  <span className="mt-1 text-xs font-normal text-[var(--muted)]">
                    {formatResumeSize(selectedResume.size)}. Choose again to
                    replace.
                  </span>
                </>
              ) : (
                <span className="text-sm font-normal">
                  Choose a synthetic resume or CV
                </span>
              )}
            </span>
          </label>
          <FieldError id="resume-error" message={errors.resume?.message} />
        </div>

        <label className="mt-6 flex items-start gap-3 rounded-2xl bg-[var(--cream-deep)] p-4 font-medium">
          <input
            type="checkbox"
            className="mt-1 size-4 accent-[var(--green)]"
            aria-invalid={Boolean(errors.acknowledgement)}
            aria-describedby={
              errors.acknowledgement ? "acknowledgement-error" : undefined
            }
            disabled={isSubmitting}
            {...register("acknowledgement")}
          />
          <span>
            I confirm that all entered details and the uploaded file are
            synthetic and contain no real PII.
          </span>
        </label>
        <FieldError
          id="acknowledgement-error"
          message={errors.acknowledgement?.message}
        />

        {isSubmitting && (
          <div className="mt-6" aria-live="polite">
            <div className="mb-2 flex justify-between text-sm font-medium">
              <span>Uploading securely to the assessment API</span>
              <span>{progress}%</span>
            </div>
            <progress className="h-2 w-full" max={100} value={progress}>
              {progress}%
            </progress>
          </div>
        )}

        {submissionError && (
          <p
            className="mt-5 rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-900"
            role="alert"
          >
            {submissionError}
          </p>
        )}

        <Button className="mt-6 w-full" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Submitting…" : "Submit synthetic lead"}
        </Button>
      </form>
    </Card>
  );
}
