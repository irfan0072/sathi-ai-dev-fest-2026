import Icon from './Icon';

/**
 * Plain-language "How this page works" box for the AI pages.
 * what: one or two sentences on the problem this page solves.
 * steps: how the AI reaches its answer, in order.
 * actions: what a person does with the result.
 * terms: [{ term, meaning }] for the words used on the page.
 */
export default function PageGuide({ what, steps = [], actions = [], terms = [] }) {
  return (
    <details open className="panel group shadow-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold">
        <Icon name="info" className="size-4 text-primary" />
        How this page works
        <span className="muted ml-auto font-normal group-open:hidden">Show</span>
        <span className="muted ml-auto hidden font-normal group-open:inline">Hide</span>
      </summary>
      <div className="grid gap-4 border-t border-base-300 px-4 py-4 text-sm md:grid-cols-3">
        <div className="flex flex-col gap-1">
          <h4 className="font-semibold">What it is for</h4>
          <p className="text-base-content/80">{what}</p>
        </div>
        <div className="flex flex-col gap-1">
          <h4 className="font-semibold">How the AI decides</h4>
          <ol className="list-inside list-decimal text-base-content/80">
            {steps.map((s) => <li key={s} className="mb-1">{s}</li>)}
          </ol>
        </div>
        <div className="flex flex-col gap-1">
          <h4 className="font-semibold">What you do with it</h4>
          <ul className="list-inside list-disc text-base-content/80">
            {actions.map((s) => <li key={s} className="mb-1">{s}</li>)}
          </ul>
        </div>
        {terms.length > 0 && (
          <dl className="grid gap-x-6 gap-y-2 border-t border-base-300 pt-3 sm:grid-cols-2 md:col-span-3 lg:grid-cols-3">
            {terms.map(({ term, meaning }) => (
              <div key={term}>
                <dt className="font-medium">{term}</dt>
                <dd className="muted">{meaning}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </details>
  );
}
